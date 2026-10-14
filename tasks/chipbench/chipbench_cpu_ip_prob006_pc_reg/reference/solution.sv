`define OK 12
`define INCORRECT 13
`define RstEnable 1'b1
`define RstDisable 1'b0
`define NoStop 1'b0
`define RegBus 31:0
`define InstAddrBus 31:0
`define Branch 1'b1
`define ChipDisable 1'b0
`define ChipEnable 1'b1

module TopModule(

	input	wire										clk,
	input wire										rst,

	//Information from the control module
	input wire[5:0]               stall,
	input wire                    flush,
	input wire[`RegBus]           new_pc,

	//Information from the decode stage
	input wire                    branch_flag_i,
	input wire[`RegBus]           branch_target_address_i,
	
	output reg[`InstAddrBus]			pc,
	output reg                    ce
	
);

	always @ (posedge clk) begin
		if (ce == `ChipDisable) begin
			pc <= 32'h00000000;
		end else begin
			if(flush == 1'b1) begin
				pc <= new_pc;
			end else if(stall[0] == `NoStop) begin
				if(branch_flag_i == `Branch) begin
					pc <= branch_target_address_i;
				end else begin
		  		pc <= pc + 4'h4;
		  	end
			end
		end
	end

	always @ (posedge clk) begin
		if (rst == `RstEnable) begin
			ce <= `ChipDisable;
		end else begin
			ce <= `ChipEnable;
		end
	end

endmodule
