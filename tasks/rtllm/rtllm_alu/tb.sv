`timescale 1ns / 1ps

module tb();
    // 转换器新增：一个样本表示一次完整上游测试台判定。
    integer benchmark_error = 0;
    integer benchmark_completed = 0;
    task benchmark_done(input integer passed);
      begin
        benchmark_completed = 1;
        $display("Mismatches: %0d in 1 samples", (!passed || benchmark_error != 0));
        $finish;
      end
    endtask
    final begin
      if (!benchmark_completed)
        $display("Mismatches: 1 in 0 samples");
    end
    initial begin
      #100000000;
      $display("TIMEOUT: upstream testbench did not complete");
      $finish;
    end


    reg [31:0] a;
    reg [31:0] b;
    reg [5:0] aluc;
    wire [31:0] r;
    wire zero;
    wire carry;
    wire negative;
    wire overflow;
    wire flag;
    reg[4:0]cnt;
    
    TopModule uut(a,b,aluc,r,zero,carry,negative,overflow,flag);

    parameter ADD = 6'b100000;
    parameter ADDU = 6'b100001;
    parameter SUB = 6'b100010;
    parameter SUBU = 6'b100011;
    parameter AND = 6'b100100;
    parameter OR = 6'b100101;
    parameter XOR = 6'b100110;
    parameter NOR = 6'b100111;
    parameter SLT = 6'b101010;
    parameter SLTU = 6'b101011;
    parameter SLL = 6'b000000;
    parameter SRL = 6'b000010;
    parameter SRA = 6'b000011;
    parameter SLLV = 6'b000100;
    parameter SRLV = 6'b000110;
    parameter SRAV = 6'b000111;
    parameter JR = 6'b001000;
    parameter LUI = 6'b001111;

    reg[5:0]opcodes[0:31];
    reg[31:0]reference[0:31];
    reg error=0;
    integer file_open;
    initial begin

    reference[0] = 'h0000003d;
reference[1] = 'h0000003d;
reference[2] = 'hfffffffb;
reference[3] = 'hfffffffb;
reference[4] = 'h00000000;
reference[5] = 'h0000003d;
reference[6] = 'h0000003d;
reference[7] = 'hffffffc2;
reference[8] = 'h00000001;
reference[9] = 'h00000001;
reference[10] = 'h10000000;
reference[11] = 'h00000000;
reference[12] = 'h00000000;
reference[13] = 'h10000000;
reference[14] = 'h00000000;
reference[15] = 'h00000000;
reference[16] = 'h001c0000;

    opcodes[0]=ADD;
    opcodes[1]=ADDU;
    opcodes[2]=SUB;
    opcodes[3]=SUBU;
    opcodes[4]=AND;
    opcodes[5]=OR;
    opcodes[6]=XOR;
    opcodes[7]=NOR;
    opcodes[8]=SLT;
    opcodes[9]=SLTU;
    opcodes[10]=SLL;
    opcodes[11]=SRL;
    opcodes[12]=SRA;
    opcodes[13]=SLLV;
    opcodes[14]=SRLV;
    opcodes[15]=SRAV;
    //opcodes[16]=JR;
    opcodes[16]=LUI;
    a=32'h0000001c;
    b=32'h00000021;
    #5;

    cnt = 0;

    
    for(cnt=0;cnt<17;cnt=cnt+1)
        begin
        #5;
        aluc=opcodes[cnt];
        #5;
        error=error|(reference[cnt]!=r);
    end

	if(error==0)
	begin
		begin $display("===========Your Design Passed==========="); benchmark_done(1); end
        end
	else
	begin
		begin $display("===========Error==========="); benchmark_done(0); end
	end
    $finish;
    end
endmodule
